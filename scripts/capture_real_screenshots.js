const { spawn } = require('child_process');
const path = require('path');
const puppeteer = require('puppeteer-core');
const http = require('http');

const CHROME_PATH = 'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe';
const PORT = 8009;
const URL = `http://127.0.0.1:${PORT}/dashboard`;
const HEALTH_URL = `http://127.0.0.1:${PORT}/health`;
const PYTHON_PATH = path.resolve(__dirname, '..', '.venv', 'Scripts', 'python.exe');

function waitForServer(retries = 30) {
  return new Promise((resolve, reject) => {
    let count = 0;
    const interval = setInterval(() => {
      count++;
      http.get(HEALTH_URL, (res) => {
        if (res.statusCode === 200) {
          clearInterval(interval);
          resolve();
        }
      }).on('error', () => {
        if (count >= retries) {
          clearInterval(interval);
          reject(new Error('Server failed to start in time'));
        }
      });
    }, 400);
  });
}

async function capture() {
  console.log('1. Starting ContextForge server on port', PORT);
  const server = spawn(PYTHON_PATH, ['-m', 'contextforge.cli.main', 'serve', '--port', PORT.toString()], {
    cwd: path.resolve(__dirname, '..'),
    stdio: 'ignore'
  });

  try {
    await waitForServer();
    console.log('2. Server is healthy. Launching Chrome...');

    const browser = await puppeteer.launch({
      executablePath: CHROME_PATH,
      headless: true,
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--disable-gpu',
        '--hide-scrollbars'
      ]
    });

    const page = await browser.newPage();

    // 1. Desktop High-Res View (1440x960, 2x DPR)
    console.log('3. Capturing Desktop Dashboard (1440x960 @ 2x)...');
    await page.setViewport({ width: 1440, height: 960, deviceScaleFactor: 2 });
    await page.goto(URL, { waitUntil: 'networkidle2' });
    await new Promise(r => setTimeout(r, 1200));

    // Trigger interactive playground compression to populate output & metrics
    try {
      await page.click('#compressBtn');
      await new Promise(r => setTimeout(r, 800));
    } catch (e) {
      console.warn('Could not click compressBtn:', e.message);
    }

    const desktopPath = path.resolve(__dirname, '..', 'docs', 'images', 'dashboard.png');
    await page.screenshot({ path: desktopPath, fullPage: false });
    console.log('✓ Saved Desktop screenshot to', desktopPath);

    // 2. Diff Viewer Tab Screenshot
    console.log('4. Capturing Diff Viewer tab...');
    try {
      await page.click('#tabDiff');
      await new Promise(r => setTimeout(r, 600));
      const diffPath = path.resolve(__dirname, '..', 'docs', 'images', 'diff_viewer.png');
      await page.screenshot({ path: diffPath, fullPage: false });
      console.log('✓ Saved Diff Viewer screenshot to', diffPath);
    } catch (e) {
      console.warn('Could not click tabDiff:', e.message);
    }

    // 3. Mobile Responsive View (414x896, 2x DPR)
    console.log('5. Capturing Mobile Responsive view (414x896 @ 2x)...');
    await page.setViewport({ width: 414, height: 896, deviceScaleFactor: 2, isMobile: true, hasTouch: true });
    try {
      await page.click('#tabOutput');
      await new Promise(r => setTimeout(r, 600));
    } catch (e) {}

    const mobilePath = path.resolve(__dirname, '..', 'docs', 'images', 'dashboard_mobile.png');
    await page.screenshot({ path: mobilePath, fullPage: false });
    console.log('✓ Saved Mobile screenshot to', mobilePath);

    await browser.close();
    console.log('6. All screenshots captured successfully.');
  } finally {
    server.kill();
    console.log('7. Server stopped.');
  }
}

capture().catch(err => {
  console.error('Error during capture:', err);
  process.exit(1);
});
