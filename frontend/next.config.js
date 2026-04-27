/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Static export for S3 + CloudFront hosting (matches the LUNA cloud architecture).
  // `npm run build` will produce an `out/` folder of plain HTML/JS/CSS files
  // that can be uploaded directly to an S3 bucket configured for static hosting.
  output: "export",
  // Append trailing slashes so URLs work cleanly in S3 (which serves /login/ as /login/index.html)
  trailingSlash: true,
  // Disable Next.js Image optimization since static export has no server to do it
  images: { unoptimized: true },
};

module.exports = nextConfig;
