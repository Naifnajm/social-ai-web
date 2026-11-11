/**
 * Passkeys in the browser (WebAuthn): the server sends options as JSON with base64url strings; the browser API
 * wants ArrayBuffers, and its answer goes back as base64url again.
 *
 *   if (passkeysSupported()) await signInWithPasskey()          // Face ID / Touch ID / Windows Hello / a phone
 *   await addPasskey("iPhone")                                   // from the profile page, signed in
 */
import { api } from "./api";
import type { Me } from "./session";

type Json = Record<string, unknown>;

const toBytes = (value: string) => {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/") + "===".slice((value.length + 3) % 4);
  return Uint8Array.from(atob(base64), (c) => c.charCodeAt(0)).buffer;
};
const toText = (buffer: ArrayBuffer | null) => {
  if (!buffer) return null;
  let binary = "";
  new Uint8Array(buffer).forEach((b) => (binary += String.fromCharCode(b)));
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
};
const descriptors = (list: unknown) =>
  ((list as { id: string; type: string; transports?: string[] }[] | undefined) ?? []).map((d) => ({ ...d, id: toBytes(d.id) })) as PublicKeyCredentialDescriptor[];

export const passkeysSupported = () => typeof window !== "undefined" && !!window.PublicKeyCredential && !!navigator.credentials;

/** A name for the passkey the person is adding, from the device they are on. */
export function deviceName() {
  const ua = navigator.userAgent;
  if (/iPhone/.test(ua)) return "iPhone";
  if (/iPad/.test(ua)) return "iPad";
  if (/Android/.test(ua)) return "Android";
  if (/Mac OS X/.test(ua)) return "Mac";
  if (/Windows/.test(ua)) return "Windows";
  return "Passkey";
}

export async function addPasskey(name: string) {
  const { token, options } = await api.post<{ token: string; options: Json }>("/auth/passkeys/register");
  const user = options.user as Json;
  const credential = (await navigator.credentials.create({
    publicKey: {
      ...(options as unknown as PublicKeyCredentialCreationOptions),
      challenge: toBytes(options.challenge as string),
      user: { ...(user as unknown as PublicKeyCredentialUserEntity), id: toBytes(user.id as string) },
      excludeCredentials: descriptors(options.excludeCredentials),
    },
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("cancelled");
  const response = credential.response as AuthenticatorAttestationResponse;
  return api.post("/auth/passkeys/register/verify", {
    token, name,
    credential: {
      id: credential.id, rawId: toText(credential.rawId), type: credential.type, clientExtensionResults: {},
      response: {
        clientDataJSON: toText(response.clientDataJSON), attestationObject: toText(response.attestationObject),
        transports: typeof response.getTransports === "function" ? response.getTransports() : undefined,
      },
    },
  });
}

export async function signInWithPasskey() {
  const { token, options } = await api.post<{ token: string; options: Json }>("/auth/passkeys/login");
  const credential = (await navigator.credentials.get({
    publicKey: {
      ...(options as unknown as PublicKeyCredentialRequestOptions),
      challenge: toBytes(options.challenge as string),
      allowCredentials: descriptors(options.allowCredentials),
    },
  })) as PublicKeyCredential | null;
  if (!credential) throw new Error("cancelled");
  const response = credential.response as AuthenticatorAssertionResponse;
  return api.post<{ me: Me }>("/auth/passkeys/login/verify", {
    token,
    credential: {
      id: credential.id, rawId: toText(credential.rawId), type: credential.type, clientExtensionResults: {},
      response: {
        clientDataJSON: toText(response.clientDataJSON), authenticatorData: toText(response.authenticatorData),
        signature: toText(response.signature), userHandle: toText(response.userHandle),
      },
    },
  });
}

/** The person closed the Face ID / Touch ID sheet: not an error worth showing. */
export const isCancel = (err: unknown) =>
  err instanceof Error && (err.name === "NotAllowedError" || err.name === "AbortError" || err.message === "cancelled");
