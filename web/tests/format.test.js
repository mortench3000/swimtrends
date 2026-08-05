import { expect, test } from 'vitest'
import { formatTime, formatInt, formatPoints, formatDelta, formatShare } from '../src/lib/format.js'

test('formatTime handles sub-minute and over-minute and null', () => {
  expect(formatTime(5821)).toBe('58.21')
  expect(formatTime(6248)).toBe('1:02.48')
  expect(formatTime(null)).toBe('–')
})
test('formatInt uses da-DK grouping', () => {
  expect(formatInt(1234)).toBe('1.234')   // da-DK thousands sep is a dot
  expect(formatInt(null)).toBe('–')
})
test('formatPoints appends unit', () => {
  expect(formatPoints(945)).toBe('945 p')
})
test('formatShare rounds to whole percent and skips a missing total', () => {
  expect(formatShare(162, 447)).toBe('36 %')
  expect(formatShare(5, 28)).toBe('18 %')
  expect(formatShare(null, 447)).toBeNull()
  expect(formatShare(162, 0)).toBeNull()
})
test('formatDelta direction respects lowerIsBetter', () => {
  expect(formatDelta(100, 120, { lowerIsBetter: true }).dir).toBe('good') // faster/smaller
  expect(formatDelta(320, 300, { lowerIsBetter: false }).dir).toBe('good') // more entrants
  expect(formatDelta(300, 300, {}).dir).toBe('flat')
})
