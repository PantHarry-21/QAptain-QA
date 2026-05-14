import 'server-only';
import { NextResponse } from 'next/server';
import { prisma } from '@/lib/prisma';

export const dynamic = 'force-dynamic';
export const revalidate = 0;
export const fetchCache = 'force-no-store';
export const runtime = 'nodejs';

export async function GET(req: Request, context: { params: Promise<{ token?: string }> }) {
  try {
    const { token = '' } = await context.params;

    if (!token) {
      return NextResponse.redirect(new URL('/login?error=Activation token missing', req.url));
    }

    const user = await prisma.user.findFirst({
      where: { activationToken: token },
    });

    if (!user) {
      return NextResponse.redirect(new URL('/login?error=Invalid or expired activation link', req.url));
    }

    if (user.emailVerified) {
      return NextResponse.redirect(
        new URL('/login?message=Account already activated. Please log in.', req.url),
      );
    }

    await prisma.user.update({
      where: { id: user.id },
      data: { emailVerified: new Date(), activationToken: null },
    });

    return NextResponse.redirect(
      new URL('/login?message=Account activated successfully! You can now log in.', req.url),
    );
  } catch (error) {
    console.error('Activation API error:', error);
    return NextResponse.redirect(new URL('/login?error=Internal server error', req.url));
  }
}
