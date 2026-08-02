export interface Session {
  id: string
  preview?: string
  message_count?: number
  space?: string
}
export interface Message {
  role: 'user' | 'assistant' | 'sys'
  content: string
}
export interface Activity {
  id: string
  type: string
  action: string
  detail: string
  ts: number
  status?: 'run' | 'ok' | 'err'
}
export interface Meta {
  provider?: string
  model?: string
  tools?: number
  status?: string
  memories?: number
  skills?: number
  sessions?: number
}
