"use client";

import { useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { getToken } from "../lib/api";

// Guards every screen. There is no server session — the token in local storage
// is the whole of sign-in — so this only has to answer "is there a token?" and
// send them to /login if not. A 401 mid-session is handled in lib/api.js,
// which clears the token and redirects from wherever the call was made.
export default function TokenGate({ children }) {
  const router = useRouter();
  const pathname = usePathname();
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (getToken()) {
      setReady(true);
      return;
    }
    const next = encodeURIComponent(pathname || "/");
    router.replace(`/login?next=${next}`);
  }, [router, pathname]);

  // Nothing until we know: rendering children first would fire an API call
  // with no token and bounce through a 401 to get to the same place.
  if (!ready) return null;

  return children;
}
