import Core from './core.js';

const domestic={
  ...Core.LEAGUE_FILES, CHAMPIONSHIP:'E1', ENGLAND_LEAGUE_1:'E2', ENGLAND_LEAGUE_2:'E3',
  BUNDES_2:'D2', SERIEB:'I2', SEGUNDA:'SP2', LIGUE2:'F2',
  PORTUGAL:'P1', NETHERLANDS:'N1', BELGIUM:'B1', TURKEY:'T1'
};
const descriptors=[
  ...Object.entries(domestic).map(([code,division])=>[code,{family:'domestic',division}]),
  ['UCL',{family:'international',league:'ucl'}],
  ['UEL',{family:'international',league:'uel2026'}],
  ['UECL',{family:'international',league:'uecl2026'}],
  ['UPL',{family:'domestic',missing:'NO_VALIDATED_UKRAINE_RESULTS_FEED'}]
];
export const paperCompetitions=new Map(descriptors);
export const paperDomestic=Object.freeze(domestic);
export const csvSeasons=['2425','2526','2627'];
export const internationalFiles=[
  ['UCL','ucl24',2024],['UCL','ucl',2025],['UCL','ucl',2026],
  ['UEL','uel24',2024],['UEL','uel2026',2026],['UECL','uecl2026',2026]
];
