/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_API_URL?: string
  // Фича-флаг «Добавить документ» (Upload-Pipeline). '1' — показать кнопку/модал.
  readonly VITE_FEATURE_UPLOAD?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
