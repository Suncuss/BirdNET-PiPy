export function getDisplayCommonName(item) {
  if (!item) return ''
  return item.display_common_name || item.common_name || ''
}

export function getDisplaySpeciesName(item) {
  if (!item) return ''
  return item.displaySpecies || item.species || ''
}

export function matchesBirdQuery(item, rawQuery) {
  const query = (rawQuery || '').trim().toLowerCase()
  if (!query) return true

  const haystacks = [
    item?.display_common_name,
    item?.common_name,
    item?.scientific_name,
    item?.displaySpecies,
    item?.species,
  ]

  return haystacks.some(value => (value || '').toLowerCase().includes(query))
}
