export const PAGE_SIZES = [10, 20, 50, 100]
export const TIMEZONES = ['Asia/Shanghai', 'UTC']
export const HOURS = Array.from({ length: 24 }, (_, value) => ({ label: `${String(value).padStart(2, '0')} 时`, value }))
export const MINUTES = [0, 5, 10, 15, 20, 30, 45, 50, 55].map(value => ({ label: `${String(value).padStart(2, '0')} 分`, value }))
export const ASSERT_OPERATORS = [
  { label: '等于', value: 'eq' }, { label: '不等于', value: 'neq' }, { label: '存在', value: 'exists' },
  { label: '不存在', value: 'not_exists' }, { label: '包含', value: 'contains' }, { label: '匹配正则', value: 'regex' },
  { label: '大于', value: 'gt' }, { label: '小于', value: 'lt' },
]
