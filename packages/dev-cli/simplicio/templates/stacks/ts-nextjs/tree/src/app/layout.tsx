import type { ReactNode } from "react";

export const metadata = {
  title: "{project_name}",
  description: "{goal}",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
