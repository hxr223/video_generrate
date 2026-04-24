import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "视频生成工作台",
  description: "基于 Seedance 的视频生成平台工作台"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body>{children}</body>
    </html>
  );
}
