/* Settlement distributions derived from the model's score grid. */
export const grades = ['loss', 'half_loss', 'push', 'half_win', 'win'];
const round = value => Number(value.toFixed(6));
const grade = (market, home, away) => {
  const { kind, side, line } = market;
  if (kind === '1X2') return (home > away ? 'home' : home < away ? 'away' : 'draw') === side ? 'win' : 'loss';
  if (kind === 'DC') return (side === '1X' ? home >= away : side === 'X2' ? home <= away : home !== away) ? 'win' : 'loss';
  if (kind === 'BTTS') return ((home > 0 && away > 0) === (side === 'yes')) ? 'win' : 'loss';
  const margin = kind === 'AH' || kind === 'DNB'
    ? (side === 'home' ? home - away : away - home) + line
    : (side === 'over' ? 1 : -1) * ((kind === 'TH' ? home : kind === 'TA' ? away : home + away) - line);
  const split = Math.abs(line * 4) % 2 === 1 ? 0.25 : 0;
  return grades[2 + Math.sign(margin - split) + Math.sign(margin + split)];
};

export { grade };

function market(kind, group, side, pick, line = 0) {
  return { id: [kind, side, line].join(':'), kind, market: group, side, pick, line };
}

export const standardMarkets = [
  market('1X2', '1X2', 'home', 'П1'), market('1X2', '1X2', 'draw', 'Х'), market('1X2', '1X2', 'away', 'П2'),
  ...['1X', 'X2', '12'].map(side => market('DC', 'Двойной шанс', side, side)),
  ...['home', 'away'].map(side => market('DNB', 'DNB', side, side === 'home' ? 'П1' : 'П2')),
  ...[-1.5, -1, -0.75, -0.5, -0.25, 0.25, 0.5, 0.75, 1, 1.5].flatMap(line =>
    ['home', 'away'].map(side => market('AH', 'Азиатская фора', side, (side === 'home' ? 'Ф1 ' : 'Ф2 ') + (line > 0 ? '+' : '') + line, line))),
  ...[1.5, 2, 2.25, 2.5, 2.75, 3, 3.5].flatMap(line =>
    [market('TG', 'Тотал', 'over', 'ТБ ' + line, line), market('TG', 'Тотал', 'under', 'ТМ ' + line, line)]),
  market('BTTS', 'ОЗ', 'yes', 'Да'), market('BTTS', 'ОЗ', 'no', 'Нет'),
  ...[['TH', 'ИТ хозяев'], ['TA', 'ИТ гостей']].flatMap(([kind, group]) =>
    [0.5, 1, 1.25, 1.5, 2, 2.5].flatMap(line =>
      [market(kind, group, 'over', 'ИТБ ' + line, line), market(kind, group, 'under', 'ИТМ ' + line, line)]))
];

export function distribution(market, grid) {
  const result = Object.fromEntries(grades.map(key => [key, 0]));
  for (const { home, away, probability } of grid) result[grade(market, home, away)] += probability;
  return result;
}

export function modelMarkets(grid, baselineGrid) {
  return standardMarkets.map(spec => {
    const settlement = distribution(spec, grid);
    return {
      ...spec, settlement, baseline: distribution(spec, baselineGrid),
      probability: round(settlement.win + settlement.half_win),
      odds: null, implied: null, ev: null, source: 'MODEL_ONLY', verdict: 'пропуск'
    };
  });
}

// Proportional normalization of a single bookmaker's complete market.
export function removeMargin(prices) {
  if (![2,3].includes(prices.length) || prices.some(price=>!Number.isFinite(price)||price<=1||price>100)) return null;
  const implied = prices.map(price=>1/price);
  const total = implied.reduce((sum,probability)=>sum+probability,0);
  return {overround:total-1,probabilities:implied.map(probability=>probability/total)};
}

export function evaluateQuote(distribution, odds) {
  if (!Number.isFinite(odds) || odds <= 1 || odds > 100 ||
      !grades.every(key => Number.isFinite(distribution?.[key]) && distribution[key] >= 0 && distribution[key] <= 1) ||
      Math.abs(grades.reduce((sum, key) => sum + distribution[key], 0) - 1) > 0.0001) return null;

  const winning = distribution.win + distribution.half_win / 2;
  const losing = distribution.loss + distribution.half_loss / 2;
  const active = winning + losing;
  if (active <= 0 || winning <= 0) return null;

  // Stress shifts the effective conditional probability, holding partial stakes and pushes fixed.
  const effective = winning / active;
  const implied = 1 / odds;
  const evAt = shift => active * (odds * Math.max(0, Math.min(1, effective + shift)) - 1);
  const breakEven = 1 + losing / winning;
  return {
    implied: round(implied), equivalent_probability: round(effective),
    edge: round(effective - implied), expected_value: round(evAt(0)),
    break_even_odds: round(breakEven), odds_margin: round(odds - breakEven),
    sensitivity: Object.fromEntries([-0.05, -0.03, 0.03, 0.05].map(shift => [String(shift), round(evAt(shift))])),
    price_stress: Object.fromEntries([2, 3, 4, 5].map(percent => {
      const reduced = odds * (1 - percent / 100);
      return [percent, reduced > 1 ? round(reduced * winning - active) : null];
    }))
  };
}
