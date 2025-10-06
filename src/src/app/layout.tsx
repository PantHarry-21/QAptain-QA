import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toaster";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "AI Test Runner - Automated Testing Powered by AI",
  description: "Transform your web testing with AI-powered automation, real-time execution, and comprehensive reporting.",
  keywords: ["AI Test Runner", "Automated Testing", "Selenium", "AI", "Web Testing", "Quality Assurance"],
  authors: [{ name: "AI Test Runner Team" }],
  openGraph: {
    title: "AI Test Runner",
    description: "AI-powered automated testing with real-time execution and comprehensive reporting",
    url: "https://your-domain.com",
    siteName: "AI Test Runner",
    type: "website",
  },
  twitter: {
    card: "summary_large_image",
    title: "AI Test Runner",
    description: "AI-powered automated testing with real-time execution",
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body
        className={`${geistSans.variable} ${geistMono.variable} antialiased bg-background text-foreground`}
      >
        {children}
        <Toaster />
      </body>
    </html>
  );
}
