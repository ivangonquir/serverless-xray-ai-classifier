import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "X-Ray Classifier",
  description: "AI-assisted chest X-ray pneumonia detection on AWS",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
