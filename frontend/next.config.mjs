/** @type {import('next').NextConfig} */
const nextConfig = {
  // The API base is read at build time on the client. Defaults to the local
  // uvicorn so `npm run dev` works with no configuration at all.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000",
  },
};

export default nextConfig;
