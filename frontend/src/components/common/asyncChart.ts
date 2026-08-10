import { defineAsyncComponent, type AsyncComponentLoader, type Component } from 'vue'

import ChartErrorState from '@/components/common/ChartErrorState.vue'
import ChartLoadingState from '@/components/common/ChartLoadingState.vue'

export function createAsyncChartComponent(
  loader: AsyncComponentLoader<Component>,
): Component {
  return defineAsyncComponent({
    loader,
    loadingComponent: ChartLoadingState,
    errorComponent: ChartErrorState,
    delay: 0,
    timeout: 15_000,
    onError(_error, retry, fail, attempts) {
      if (attempts < 2) retry()
      else fail()
    },
  })
}
