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

// Only score coordinates are reusable. Each forecast supplies its own probabilities.
const gridWidth = 13;
const gradePlans = new WeakMap();

function hasStandardLayout(grid) {
  return Array.isArray(grid) && grid.length === gridWidth ** 2 &&
    grid.every(({home, away}, i) => home === Math.floor(i / gridWidth) && away === i % gridWidth);
}

function gradePlan(spec) {
  const prior = gradePlans.get(spec);
  if (prior && prior.kind === spec.kind && prior.side === spec.side && prior.line === spec.line) return prior.groups;
  const groups = Object.fromEntries(grades.map(key => [key, []]));
  for (let i = 0; i < gridWidth ** 2; i++) {
    groups[grade(spec, Math.floor(i / gridWidth), i % gridWidth)].push(i);
  }
  gradePlans.set(spec, {kind: spec.kind, side: spec.side, line: spec.line, groups});
  return groups;
}

function sumGroups(groups, grid) {
  const result = {};
  for (const key of grades) {
    let sum = 0;
    for (const index of groups[key]) sum += grid[index].probability;
    result[key] = sum;
  }
  return result;
}

export function modelMarkets(grid, baselineGrid) {
  const standard = hasStandardLayout(grid) && hasStandardLayout(baselineGrid);
  return standardMarkets.map(spec => {
    const groups = standard && gradePlan(spec);
    const settlement = groups ? sumGroups(groups, grid) : distribution(spec, grid);
    return {
      ...spec, settlement, baseline: groups ? sumGroups(groups, baselineGrid) : distribution(spec, baselineGrid),
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

// The caller supplies the provider-side decision separately from editable tour fields.
export function prematchReview(row, now) {
  const e = row?.evidence ?? {};
  const m = row?.best_candidate ?? {};
  const reasons = [];
  const time = value => typeof value === 'string' && /(?:Z|[+-]\d\d:\d\d)$/.test(value) ? Date.parse(value) : NaN;
  const cutoff = time(row?.source_cutoff), generated = time(row?.generated_at), kickoff = time(row?.kickoff);
  const observed = time(m.observed_at), quoted = time(m.quote_updated_at);
  const red = row?.risk_class === 'RED' || e.kickoff_gate === 'KICKOFF_CONFLICT' ||
    e.kickoff_gate === 'DUPLICATE_FIXTURE' || (row && !(cutoff <= generated && generated <= now && now < kickoff)) ||
    observed > cutoff || quoted > observed;
  if (red) reasons.push('TIME_OR_IDENTITY_CONFLICT');
  if (!row || e.kickoff_gate !== 'CONFIRMED' || e.fixture_timing_status !== 'confirmed') reasons.push('PREMATCH_TIME');
  if (!(quoted <= observed && observed <= cutoff && now - quoted <= 3600000) ||
      m.price_verified !== true || m.quote_timestamp_verified !== true) reasons.push('QUOTE_UNVERIFIED');
  const priced=evaluateQuote(m.settlement,m.odds);
  if (!priced || priced.expected_value !== m.ev || !(m.ev > 0) || m.value_verified !== true ||
      !Number.isFinite(m.probability) || m.probability !== round(m.settlement.win + m.settlement.half_win))
    reasons.push('EV_GATE');
  if (!(Number.isInteger(row?.sample_n) && row.sample_n >= 6 && e.lineups_gate === 'CONFIRMED' &&
      e.latest_training_date && /^\d{4}-\d{2}-\d{2}$/.test(e.latest_training_date) &&
      Date.parse(e.latest_training_date+'T23:59:59.999Z') < cutoff)) reasons.push('DATA_QUALITY');
  if (e.fit_gate !== 'VERIFIED') reasons.push('TACTICAL_FIT');
  if (e.public_trap_gate !== 'VERIFIED') reasons.push('PUBLIC_TRAP');
  if (e.death_test_gate !== 'VERIFIED' || m.death_test !== 'PASS_CONDITIONAL' ||
      !(Number.isFinite(m.sensitivity?.['-0.05']) && m.sensitivity['-0.05'] > 0 && priced?.sensitivity['-0.05'] === m.sensitivity['-0.05'])) reasons.push('DEATH_TEST');
  const main = ['1X2','Двойной шанс','DNB','Фора','Азиатская фора','Тотал','ОЗ','Индивидуальный тотал','ИТ хозяев','ИТ гостей'];
  if (e.alternative_market_gate !== 'VERIFIED' || !main.includes(m.alternative?.market) ||
      m.alternative.market === m.market || !Number.isFinite(m.alternative.ev) || !(m.ev > m.alternative.ev) ||
      (!main.includes(m.market) && !(typeof e.market_rationale==='string' && e.market_rationale.trim())))
    reasons.push('ALTERNATIVE_MARKET');
  if (m.market === 'ЖК' && !(e.referee_gate === 'VERIFIED' && typeof e.referee === 'string' && e.referee.trim() &&
      Number.isFinite(e.yc_game) && e.yc_game > 0 && Number.isFinite(e.yc_foul) && e.yc_foul > 0 &&
      e.low_card_risk === true && e.rules_confirmed === true && e.no_cleaner_market === true)) reasons.push('REFEREE_GATE');
  if(e.selection_basis !== 'SPORTING_EDGE') reasons.push('ODDS_FILLER');
  if (e.calibration_gate !== 'VERIFIED' || !['A','B'].includes(row?.risk_class)) reasons.push('CONFIDENCE');
  if (row?.verdict !== 'играбельно' || !Array.isArray(e.pass_reasons) || e.pass_reasons.length) reasons.push('SOURCE_PASS');
  const riskClass = red ? 'RED' : Number.isFinite(m.ev) && m.ev <= 0 ? 'D' : reasons.length ? 'C' : row.risk_class;
  return {eligible: reasons.length === 0, riskClass, reasons};
}
