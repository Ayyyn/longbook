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
  metadataBase: new URL("https://longbook.co"),
  title: {
    default: "Longbook — nothing should depend on remembering it",
    template: "%s · Longbook",
  },
  description:
    "Longbook keeps track of your orders, payments, customers and " +
    "commitments, and tells you what needs attention. Works with the records " +
    "you already keep. No double entry, no new way of working.",
  openGraph: {
    title: "Longbook — nothing should depend on remembering it",
    description:
      "Orders, payments, customers and follow-ups, kept together. It learns " +
      "how your business works instead of making you fit a template.",
    url: "https://longbook.co",
    siteName: "Longbook",
    locale: "en_IN",
    type: "website",
  },
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
