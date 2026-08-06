import type { IndexCollection } from '@/types'

export interface IndexActionAvailability {
  rebuild: boolean
  rollback: boolean
  terminate: boolean
  cleanup: boolean
}

export function getIndexActionAvailability(
  item: IndexCollection,
  rebuildingId: string | null,
  hasPrevious: boolean,
): IndexActionAvailability {
  const idle = rebuildingId === null
  return {
    rebuild: item.lifecycle === 'active' && idle,
    rollback: item.lifecycle === 'active' && hasPrevious && idle,
    terminate: item.lifecycle === 'building' || rebuildingId === item.id,
    cleanup: item.lifecycle !== 'active' && item.lifecycle !== 'building' && idle,
  }
}
