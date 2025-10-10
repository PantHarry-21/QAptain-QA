
// scripts/download-chromium.mjs
import chromium from '@sparticuz/chromium';

console.log('Starting Chromium download during post-install...');

async function downloadBrowser() {
  try {
    const executablePath = await chromium.executablePath();
    console.log(`Chromium downloaded successfully to: ${executablePath}`);
    process.exit(0);
  } catch (error) {
    console.error('Failed to download Chromium:', error);
    // Exit with 0 to avoid breaking the build if the download fails.
    // The runtime will attempt the download again.
    process.exit(0);
  }
}

downloadBrowser();
