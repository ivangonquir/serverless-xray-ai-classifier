import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "LUNA — Lung kNowledge Assistant",
  description:
    "Clinical Decision Support System for early lung cancer screening.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-abyss text-ice">{children}</body>
    </html>
  );
}
