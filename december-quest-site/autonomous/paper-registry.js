import Core from './core.js';
import { decemberSports } from './odds-gateway.js';

const domestic={
  ...Core.LEAGUE_FILES, CHAMPIONSHIP:'E1', ENGLAND_LEAGUE_1:'E2', ENGLAND_LEAGUE_2:'E3',
  BUNDES_2:'D2', SERIEB:'I2', SEGUNDA:'SP2', LIGUE2:'F2',
  PORTUGAL:'P1', NETHERLANDS:'N1', BELGIUM:'B1', TURKEY:'T1', NATIONAL_LEAGUE:'EC'
};
const descriptors=[
  ...Object.entries(domestic).map(([code,division])=>[code,{family:'domestic',division}]),
  ['UCL',{family:'international',league:'ucl'}],
  ['UEL',{family:'international',league:'uel2026'}],
  ['UECL',{family:'international',league:'uecl2026'}],
  ['DFB_POKAL',{family:'international',league:'dfb'}],
  ['UPL',{family:'domestic',missing:'NO_VALIDATED_UKRAINE_RESULTS_FEED'}]
];
export const paperCompetitions=new Map(descriptors);
export const paperDomestic=Object.freeze(domestic);
export const paperOddsSports=Object.freeze({...decemberSports,
  CHAMPIONSHIP:'soccer_efl_champ', ENGLAND_LEAGUE_1:'soccer_england_league1', ENGLAND_LEAGUE_2:'soccer_england_league2',
  BUNDES_2:'soccer_germany_bundesliga2', SERIEB:'soccer_italy_serie_b', SEGUNDA:'soccer_spain_segunda_division',
  LIGUE2:'soccer_france_ligue_two', PORTUGAL:'soccer_portugal_primeira_liga', NETHERLANDS:'soccer_netherlands_eredivisie',
  BELGIUM:'soccer_belgium_first_div', TURKEY:'soccer_turkey_super_league', UCL:'soccer_uefa_champs_league',
  UEL:'soccer_uefa_europa_league', UECL:'soccer_uefa_europa_conference_league', DFB_POKAL:'soccer_germany_dfb_pokal'
});
export const csvSeasons=['2425','2526','2627'];
export const internationalFiles=[
  ['UCL','ucl24',2024],['UCL','ucl',2025],['UCL','ucl',2026],
  ['UEL','uel24',2024],['UEL','uel2026',2026],['UECL','uecl2026',2026],
  ...[2024,2025,2026].map(season=>['DFB_POKAL','dfb',season])
];
