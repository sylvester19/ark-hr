import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "ARK HR – Bulk CV Translation Tool",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
