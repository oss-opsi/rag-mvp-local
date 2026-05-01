/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  reactStrictMode: true,
  poweredByHeader: false,
  // Le middleware Next.js (cf. middleware.ts) intercepte TOUTES les requêtes
  // (matcher = "/((?!_next/static|_next/image|favicon.ico|public/).*)").
  // Sur Next 15, le body est bufférisé en mémoire avec une limite par défaut
  // de 10 MB. Au-delà, l'upload échoue côté client avec "Load failed".
  experimental: {
    serverActions: {
      bodySizeLimit: "60mb",
    },
    middlewareClientMaxBodySize: "100mb",
  },
};

export default nextConfig;
