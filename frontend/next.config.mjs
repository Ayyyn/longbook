/** @type {import('next').NextConfig} */
const nextConfig = {
  // Cloud Run runs the server build, not a static export: the app is
  // client-rendered but still needs a Node process to serve it.
  output: "standalone",
  // The API base is read at build time on the client. Defaults to the local
  // uvicorn so `npm run dev` works with no configuration at all.
  env: {
    NEXT_PUBLIC_API_BASE: process.env.NEXT_PUBLIC_API_BASE || "http://localhost:8000",
  },
};

export default nextConfig;
