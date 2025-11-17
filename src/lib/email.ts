import nodemailer from 'nodemailer';

/**
 * Creates a nodemailer transporter based on environment variables.
 * Supports SMTP configuration via environment variables.
 * Returns null if no email configuration is found.
 */
function createTransporter(): nodemailer.Transporter | null {
  // Check if we have SMTP configuration
  const smtpHost = process.env.SMTP_HOST;
  const smtpPort = process.env.SMTP_PORT;
  const smtpUser = process.env.SMTP_USER;
  const smtpPassword = process.env.SMTP_PASSWORD;
  const smtpFrom = process.env.SMTP_FROM || smtpUser || 'noreply@qaptain.com';

  // If SMTP is configured, use it
  if (smtpHost && smtpPort && smtpUser && smtpPassword) {
    return nodemailer.createTransport({
      host: smtpHost,
      port: parseInt(smtpPort, 10),
      secure: parseInt(smtpPort, 10) === 465, // true for 465, false for other ports
      auth: {
        user: smtpUser,
        pass: smtpPassword,
      },
    });
  }

  // Fallback: Use Gmail OAuth2 if Gmail credentials are provided
  const gmailUser = process.env.GMAIL_USER;
  const gmailPassword = process.env.GMAIL_APP_PASSWORD;
  
  if (gmailUser && gmailPassword) {
    return nodemailer.createTransport({
      service: 'gmail',
      auth: {
        user: gmailUser,
        pass: gmailPassword, // Use Gmail App Password
      },
    });
  }

  // No email configuration found
  console.warn('[Email] No SMTP configuration found. Emails will not be sent.');
  console.warn('[Email] To send real emails, configure one of the following:');
  console.warn('[Email]   - SMTP: SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD');
  console.warn('[Email]   - Gmail: GMAIL_USER, GMAIL_APP_PASSWORD');
  
  // Return null to indicate email cannot be sent
  return null;
}

/**
 * Sends an activation email to the user
 */
export async function sendActivationEmail(
  email: string,
  firstName: string,
  activationToken: string,
  activationUrl: string
): Promise<void> {
  try {
    const transporter = createTransporter();
    
    // If transporter is null, email cannot be sent (no configuration)
    if (!transporter) {
      console.warn(`[Email] Cannot send activation email to ${email} - no email configuration found`);
      console.warn(`[Email] Activation URL for manual use: ${activationUrl}`);
      return; // Don't throw - allow signup to succeed
    }
    
    const fromEmail = process.env.SMTP_FROM || process.env.GMAIL_USER || process.env.SMTP_USER || 'noreply@qaptain.com';

    const mailOptions = {
      from: `QAptain <${fromEmail}>`,
      to: email,
      subject: 'Activate Your QAptain Account',
      html: `
        <!DOCTYPE html>
        <html>
        <head>
          <meta charset="utf-8">
          <meta name="viewport" content="width=device-width, initial-scale=1.0">
          <title>Activate Your Account</title>
        </head>
        <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
          <div style="background-color: #f4f4f4; padding: 20px; border-radius: 5px;">
            <h1 style="color: #333; text-align: center;">Welcome to QAptain!</h1>
            <p>Hi ${firstName},</p>
            <p>Thank you for signing up for QAptain. To complete your registration and activate your account, please click the link below:</p>
            <div style="text-align: center; margin: 30px 0;">
              <a href="${activationUrl}" 
                 style="background-color: #007bff; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; display: inline-block;">
                Activate Account
              </a>
            </div>
            <p>Or copy and paste this URL into your browser:</p>
            <p style="word-break: break-all; color: #666; font-size: 12px;">${activationUrl}</p>
            <p>This activation link will expire in 7 days.</p>
            <p>If you didn't create an account with QAptain, please ignore this email.</p>
            <hr style="border: none; border-top: 1px solid #eee; margin: 20px 0;">
            <p style="color: #666; font-size: 12px;">© ${new Date().getFullYear()} QAptain. All rights reserved.</p>
          </div>
        </body>
        </html>
      `,
      text: `
        Welcome to QAptain!
        
        Hi ${firstName},
        
        Thank you for signing up for QAptain. To complete your registration and activate your account, please visit the following link:
        
        ${activationUrl}
        
        This activation link will expire in 7 days.
        
        If you didn't create an account with QAptain, please ignore this email.
        
        © ${new Date().getFullYear()} QAptain. All rights reserved.
      `,
    };

    const info = await transporter.sendMail(mailOptions);
    console.log('[Email] Activation email sent:', info.messageId);
    
    // If using ethereal.email (test mode), log the preview URL
    if (info.messageId && nodemailer.getTestMessageUrl) {
      const previewUrl = nodemailer.getTestMessageUrl(info);
      if (previewUrl) {
        console.log('[Email] Preview URL (test mode):', previewUrl);
      }
    }
  } catch (error) {
    console.error('[Email] Error sending activation email:', error);
    // Don't throw - we don't want to fail signup if email fails
    // Just log the error
    throw error; // Actually, let's throw so the caller knows
  }
}

