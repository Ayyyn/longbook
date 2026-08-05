import "./globals.css";
import Tabs from "./components/Tabs";

export const metadata = {
  title: "Textile Ops",
  description: "Orders, payments and the review queue",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  themeColor: "#0b6b3a",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en">
      <body>
        <div className="shell">{children}</div>
        <Tabs />
      </body>
    </html>
  );
}
