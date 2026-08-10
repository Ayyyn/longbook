import { Instrument_Serif, Inter } from "next/font/google";
import "./globals.css";
import Tabs from "./components/Tabs";
import AccountMenu from "./components/AccountMenu";

// Two faces, one job each. The serif carries headlines and the money figures —
// it is what makes the thing look considered rather than generated. Inter does
// everything that has to be read quickly at small sizes in bright light.
//
// next/font self-hosts both at build time, so there is no third-party request
// at runtime and no layout shift while a webfont loads on market wifi.
const display = Instrument_Serif({
  weight: "400",
  subsets: ["latin"],
  style: ["normal", "italic"],
  variable: "--font-display",
  display: "swap",
});

const sans = Inter({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

export const metadata = {
  title: "Textile Ops",
  description: "Your WhatsApp is already your order book. We just write it down.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#0d5c34",
};

export default function RootLayout({ children }) {
  return (
    <html lang="en" className={`${sans.variable} ${display.variable}`}>
      <body>
        <AccountMenu />
        <div className="shell">{children}</div>
        <Tabs />
      </body>
    </html>
  );
}
