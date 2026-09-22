/**
 * Temporarily store files and requirements to be uploaded
 * Used for immediate redirect after clicking "Start Engine" on the homepage, API calls are made on the Process page
 */
import { reactive } from 'vue'

const state = reactive({
  files: [],
  simulationRequirement: '',
  domain: 'auto',
  isPending: false
})

export function setPendingUpload(files, requirement, domain = 'auto') {
  state.files = files
  state.simulationRequirement = requirement
  state.domain = domain
  state.isPending = true
}

export function getPendingUpload() {
  return {
    files: state.files,
    simulationRequirement: state.simulationRequirement,
    domain: state.domain,
    isPending: state.isPending
  }
}

export function clearPendingUpload() {
  state.files = []
  state.simulationRequirement = ''
  state.domain = 'auto'
  state.isPending = false
}

export default state
