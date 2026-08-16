import { Instrument_Serif, Inter } from "next/font/google";
import "./globals.css";
import Tabs from "./components/Tabs";
import NoteShortcut from "./components/NoteShortcut";
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
    default: "Longbook — your business has a lot going on",
    template: "%s · Longbook",
  },
  // Kept in step with the hero on the home page. These are what someone reads
  // in a WhatsApp forward, which for this audience is where most first
  // impressions actually happen — so a stale line here is a stale pitch.
  description:
    "Orders, payments, customers and commitments are scattered across chats, " +
    "bills and your own memory. Longbook brings them together and turns them " +
    "into the few things worth doing today.",
  openGraph: {
    title: "Your business has a lot going on. Longbook keeps up.",
    description:
      "Orders, payments, customers and commitments, brought together from the " +
      "records you already keep.",
    url: "https://longbook.co",
    siteName: "Longbook",
    locale: "en_IN",
    type: "website",
    // JPEG at 1200x630. WebP is not reliably rendered by WhatsApp or LinkedIn
    // previews, and a card that silently shows no image is worse than a
    // slightly larger file.
    images: [
      {
        url: "/og-image.jpg",
        width: 1200,
        height: 630,
        alt: "Nine small businesses side by side: a jeweller, a fabric shop, a warehouse, a chemist, a machine works, a service desk, an electrical shop, a produce market and a hardware store.",
      },
    ],
  },
  twitter: {
    card: "summary_large_image",
    title: "Your business has a lot going on. Longbook keeps up.",
    description:
      "Orders, payments, customers and commitments, brought together from the " +
      "records you already keep.",
    images: ["/og-image.jpg"],
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
        <NoteShortcut />
        <Tabs />
      </body>
    </html>
  );
}
