// Фиксированная палитра и подписи типов узлов/связей (единый источник для UI и графа).
import type { Confidence, EdgeType, NodeType } from '../api/types'

// Палитра типов узлов — гармоничная производная от фирменного синего «Норникеля»
// (стр. 35 брендбука), различимая на светлом холсте. Синхронизирована с tailwind node.*
export const NODE_COLORS: Record<NodeType, string> = {
  Material: '#0077C8',    // фирменный синий
  Process: '#17A2A2',     // бирюзовый
  Equipment: '#E07B00',   // оранжевый
  Condition: '#7A5AC2',   // фиолетовый
  Assertion: '#D6336C',   // пурпурный
  Publication: '#64748B', // серо-синий
  Expert: '#C79200',      // золотой
  Facility: '#2E8B72',    // изумрудный
  Parameter: '#6D5BB0',   // сине-фиолетовый
  Measurement: '#0E9AA7', // сине-циан
  Experiment: '#A5744B',  // коричневый
}

export const NODE_LABELS: Record<NodeType, string> = {
  Material: 'Материал',
  Process: 'Процесс',
  Equipment: 'Оборудование',
  Condition: 'Условие',
  Assertion: 'Утверждение',
  Publication: 'Публикация',
  Expert: 'Эксперт',
  Facility: 'Лаборатория/объект',
  Parameter: 'Параметр',
  Measurement: 'Измерение',
  Experiment: 'Эксперимент',
}

// Легенда графа — основная палитра из ТЗ (8 типов) + доп. типы онтологии.
export const LEGEND_PRIMARY: NodeType[] = [
  'Material', 'Process', 'Equipment', 'Condition',
  'Assertion', 'Publication', 'Expert', 'Facility',
]
export const LEGEND_SECONDARY: NodeType[] = ['Parameter', 'Measurement', 'Experiment']

export const EDGE_LABELS: Record<EdgeType, string> = {
  uses_material: 'использует материал',
  produces_output: 'производит',
  operates_at_condition: 'при условии',
  uses_equipment: 'использует оборудование',
  measured: 'измерено',
  described_in: 'описано в',
  authored_by: 'автор',
  works_at: 'работает в',
  expert_in: 'эксперт по',
  validated_by: 'подтверждается',
  contradicts: 'противоречит',
  supersedes: 'заменяет',
  located_in: 'расположено в',
  about: 'о теме',
}

// Цепочка для подсветки: материал → процесс → оборудование → результат
export const CHAIN_TYPES: NodeType[] = ['Material', 'Process', 'Equipment']

// Бейджи достоверности — семантика high/medium/low сохранена и различима на светлой теме.
export const CONFIDENCE_META: Record<Confidence, { label: string; color: string; bg: string }> = {
  high: { label: 'Высокая', color: '#12A150', bg: 'rgba(18,161,80,0.12)' },
  medium: { label: 'Средняя', color: '#C77700', bg: 'rgba(199,119,0,0.12)' },
  low: { label: 'Низкая', color: '#E03131', bg: 'rgba(224,49,49,0.12)' },
}

// 4 golden queries из §3 плана — кликабельные примеры на экране поиска.
export const GOLDEN_QUERIES: { title: string; query: string; hint: string }[] = [
  {
    title: 'Обессоливание воды для ОФ',
    query: 'Методы обессоливания воды для обогатительных фабрик при сульфатах, хлоридах, Ca, Mg, Na 200–300 мг/л и сухом остатке ≤1000 мг/дм³',
    hint: 'сульфаты/хлориды/Ca/Mg/Na 200–300 мг/л, сухой остаток ≤1000 мг/дм³',
  },
  {
    title: 'Циркуляция католита (ЭЭ Ni)',
    query: 'Циркуляция католита при электроэкстракции никеля: технические решения и оптимальная скорость потока',
    hint: 'технические решения + оптимальная скорость циркуляции',
  },
  {
    title: 'Au, Ag, МПГ: штейн vs шлак',
    query: 'Эксперименты и публикации по распределению золота, серебра и МПГ между штейном и шлаком за последние 5 лет',
    hint: 'распределение благородных металлов, 2021–2025',
  },
  {
    title: 'Закачка шахтных вод: РФ vs зарубеж',
    query: 'Закачка шахтных вод в глубокие горизонты: сравнение практики РФ и зарубежья, технико-экономические показатели',
    hint: 'РФ vs зарубеж + ТЭП',
  },
]
