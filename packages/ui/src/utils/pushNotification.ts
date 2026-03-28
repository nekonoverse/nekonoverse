import {
  createPushSubscription,
  deletePushSubscription,
  type PushSubscriptionResponse,
} from "../api/push";
import { instance } from "../stores/instance";

/**
 * このブラウザでプッシュ通知がサポートされているか確認する。
 */
export function isPushSupported(): boolean {
  return (
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window
  );
}

/**
 * 現在の通知パーミッション状態を取得する。
 */
export function getPermissionState(): NotificationPermission {
  return Notification.permission;
}

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const rawData = atob(base64);
  const outputArray = new Uint8Array(rawData.length);
  for (let i = 0; i < rawData.length; ++i) {
    outputArray[i] = rawData.charCodeAt(i);
  }
  return outputArray;
}

function arrayBufferToBase64url(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (const byte of bytes) {
    binary += String.fromCharCode(byte);
  }
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

/**
 * プッシュ通知を購読する。
 * 1. 通知パーミッションをリクエスト
 * 2. インスタンス情報から VAPID 公開鍵を取得
 * 3. PushManager 経由で購読
 * 4. 購読情報をサーバーに送信
 */
export async function subscribeToPush(): Promise<PushSubscriptionResponse | null> {
  if (!isPushSupported()) return null;

  const permission = await Notification.requestPermission();
  if (permission !== "granted") return null;

  const vapidKey = instance()?.vapid_key;
  if (!vapidKey) return null;

  const registration = await navigator.serviceWorker.ready;
  const applicationServerKey = urlBase64ToUint8Array(vapidKey);

  const subscription = await registration.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: applicationServerKey.buffer as ArrayBuffer,
  });

  const p256dh = arrayBufferToBase64url(subscription.getKey("p256dh")!);
  const auth = arrayBufferToBase64url(subscription.getKey("auth")!);

  return createPushSubscription(subscription.endpoint, p256dh, auth);
}

/**
 * プッシュ通知の購読を解除する。
 */
export async function unsubscribeFromPush(): Promise<void> {
  try {
    await deletePushSubscription();
  } catch {
    // サーバー側の購読がなくても続行
  }

  if (!isPushSupported()) return;

  const registration = await navigator.serviceWorker.ready;
  const subscription = await registration.pushManager.getSubscription();
  if (subscription) {
    await subscription.unsubscribe();
  }
}

/**
 * 現在プッシュ通知を購読中か確認する。
 */
export async function isSubscribedToPush(): Promise<boolean> {
  if (!isPushSupported()) return false;

  try {
    const registration = await navigator.serviceWorker.ready;
    const subscription = await registration.pushManager.getSubscription();
    return subscription !== null;
  } catch {
    return false;
  }
}
