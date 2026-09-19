/** Build-time configuration. Set in the environment (or .env.production) before `npm run build`. */
export const config = {
  /** Public repository URL. When empty, no repository links are shown. */
  repoUrl: (import.meta.env.VITE_REPO_URL as string | undefined)?.replace(/\/$/, '') ?? '',
} as const

export const repoFile = (path: string): string | null => (config.repoUrl ? `${config.repoUrl}/blob/main/${path}` : null)
