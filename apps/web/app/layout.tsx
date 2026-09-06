import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = { title: "Solution Copilot", description: "可追溯的解决方案工作台" };
export default function Layout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
