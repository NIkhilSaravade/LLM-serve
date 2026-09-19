import raw from './data.json'
import type { SiteData } from './types'

/** The one typed entry point to the generated data. */
export const data = raw as unknown as SiteData
