// Drive the running dev server and screenshot it. Lives in web/ so `import
// 'playwright'` resolves against web/node_modules. See .claude/skills/run-web.
import { chromium } from 'playwright'

const OUT = process.env.OUT || '/tmp/swimtrends-shot'
const ROUTE = process.env.ROUTE || '#/c/DM-L/m/10334' // a meet with relays + both genders
const URL = `http://localhost:${process.env.PORT || 5199}/${ROUTE}`

const browser = await chromium.launch()
const page = await browser.newPage({ viewport: { width: 1100, height: 1400 }, deviceScaleFactor: 2 })
await page.goto(URL, { waitUntil: 'networkidle' })
await page.locator('h1.wordmark').waitFor() // SPA mounted (present on every route)
await page.screenshot({ path: `${OUT}.png`, fullPage: true })
console.log(`wrote ${OUT}.png`)
await browser.close()
