// Официальный фирменный блок «Норникель».
// Знак и логотип-надпись взяты из оригинального векторного файла компании
// (https://nornickel.ru/images/logo/logo-ru.svg) без каких-либо изменений цветов
// и пропорций — как того требует Стандарт «Фирменный стиль» (стр. 9, 22–23:
// «использовать только оригинальные векторные файлы»).
// Цвета оригинала: светло-синий #0089C5, тёмно-синий #0061A3, серый #5A5A59.

// Фирменный знак (лента «N» из двух полуокружностей) — точные пути из logo-ru.svg.
export function NornickelMark({ size = 34, className = '' }: { size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={(size * 42.1) / 63}
      viewBox="0 0 63.003 42.102"
      fill="none"
      className={className}
      role="img"
      aria-label="Норникель"
    >
      <path d="M21.0347 27.8313L41.9682 42V14.1687L21.0347 0V27.8313Z" fill="#0061A3" />
      <path d="M21.0346 0C9.40491 0 0 9.41205 0 21.0506C0 32.6892 9.40491 42.1012 21.0346 42.1012V0Z" fill="#0089C5" />
      <path d="M41.9681 42C53.5979 42 63.0028 32.588 63.0028 20.9494C63.0028 9.31084 53.5979 0 41.9681 0V42Z" fill="#0089C5" />
    </svg>
  )
}

// Полный фирменный блок: официальный логотип (знак + надпись «НОРНИКЕЛЬ»)
// из оригинального файла /logo-ru.svg + продуктовое имя.
export function BrandBlock() {
  return (
    <div className="space-y-1.5">
      <img src="/logo-ru.svg" alt="Норникель" className="h-8 w-auto select-none" draggable={false} />
      <div className="text-[12px] font-semibold text-accent leading-tight pl-0.5">
        Научный клубок · карта знаний R&D
      </div>
    </div>
  )
}
