import { createContext, useContext } from 'react'
import type { User } from './api'

export const UserCtx = createContext<User | null>(null)
export const useUser = () => useContext(UserCtx)!
