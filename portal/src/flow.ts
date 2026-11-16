import { useNavigate } from 'react-router-dom'

import { isChallenge, type AuthStep, type Challenge } from './api'
import { setTokens } from './auth'

/** What each sign-in page receives through router state. */
export interface FlowState<C extends Challenge = Challenge> {
  challenge: C
  email: string
}

const ROUTE: Record<Challenge['challenge'], string> = {
  NEW_PASSWORD_REQUIRED: '/new-password',
  MFA_SETUP: '/mfa-setup',
  SOFTWARE_TOKEN_MFA: '/mfa',
}

/** Move to whatever the server says comes next: another challenge page,
 *  or — once tokens arrive — the signed-in home. */
export function useAdvance() {
  const navigate = useNavigate()
  return (step: AuthStep, email: string) => {
    if (isChallenge(step)) {
      const state: FlowState = { challenge: step, email }
      navigate(ROUTE[step.challenge], { state, replace: true })
    } else {
      setTokens(step.id_token, step.refresh_token ?? null)
      navigate('/', { replace: true })
    }
  }
}
