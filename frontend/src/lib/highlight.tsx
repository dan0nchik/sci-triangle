import type { ReactNode } from 'react'

// ============================================================================
// Верифицируемость как UX-фича (приоритет жюри №2): подсветка чисел/концентраций
// в дословных фрагментах, чтобы эксперт мгновенно сверил цифру ответа с
// первоисточником. Regex по числам с единицами (мг/л, °C, м³/ч, %, ₽/м³ …).
// ============================================================================

// Единицы измерения — длинные варианты раньше коротких (для корректного матча).
const UNITS = [
  'мг/дм³', 'мг/дм3', 'мг/л', 'г/дм³', 'г/л', 'г/т', 'кг/т',
  'кВт·ч/м³', 'кВт·ч', 'м³/ч', 'м³/сут', 'л/ч', 'А/м²', 'А/дм²',
  '₽/м³', 'руб\\./м³', 'руб/м³', '\\$/м³', 'USD/m3',
  'млн\\s?₽', 'млн\\s?руб\\.?', '°C', '°С', '°',
  'м³', 'мкм', 'нм', 'мм', 'см', 'мг', 'кВт', 'МВт', 'ppm', '%', 'м',
].join('|')

// Числовой токен: опц. компаратор (≤ ≥ < > ~ ≈), число (с , . и пробелами-разрядами),
// опц. диапазон через тире.
const NUM = '[≤≥<>~≈]?\\s?\\d[\\d\\s.,]*(?:\\s?[–—-]\\s?\\d[\\d.,]*)?'

// Итоговый паттерн: pH-диапазоны | число+единица | «X %».
const PATTERN = new RegExp(
  `(pH\\s?${NUM}|${NUM}\\s?(?:${UNITS})|about\\s?\\d[\\d.,]*\\s?(?:${UNITS}))`,
  'giu',
)

/** Есть ли в тексте хоть одно проверяемое число с единицей. */
export function hasVerifiableNumber(text: string): boolean {
  PATTERN.lastIndex = 0
  return PATTERN.test(text)
}

/**
 * Разбивает текст на сегменты, оборачивая числа-с-единицами в <mark> (класс .num-hl).
 * Возвращает массив React-нод. Первый матч получает id (для скролла «проверить в источнике»).
 */
export function highlightNumbers(text: string, markIdPrefix?: string): ReactNode[] {
  const out: ReactNode[] = []
  let last = 0
  let i = 0
  let m: RegExpExecArray | null
  const re = new RegExp(PATTERN.source, 'giu')
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index))
    out.push(
      <mark
        key={`hl-${i}`}
        id={markIdPrefix && i === 0 ? `${markIdPrefix}` : undefined}
        className="num-hl"
      >
        {m[0]}
      </mark>,
    )
    last = m.index + m[0].length
    i++
    if (m[0].length === 0) re.lastIndex++ // защита от нулевого матча
  }
  if (last < text.length) out.push(text.slice(last))
  return out.length ? out : [text]
}
