/** Pick photos / videos (camera or library) and upload them to the workspace media library (`POST /api/media`). */
import * as ImagePicker from 'expo-image-picker';
import { Alert, Linking, Platform } from 'react-native';

import { api } from './api';
import { t } from './i18n';
import type { MediaItem } from './types';

const MAX_MB = { image: 20, video: 200 } as const;

async function ensurePermission(source: 'camera' | 'library'): Promise<boolean> {
  if (Platform.OS === 'web') return true;
  const current = source === 'camera' ? await ImagePicker.getCameraPermissionsAsync() : await ImagePicker.getMediaLibraryPermissionsAsync();
  if (current.granted) return true;
  const asked = current.canAskAgain
    ? source === 'camera'
      ? await ImagePicker.requestCameraPermissionsAsync()
      : await ImagePicker.requestMediaLibraryPermissionsAsync()
    : current;
  if (asked.granted) return true;
  Alert.alert(t('media.permissionTitle'), source === 'camera' ? t('media.cameraDenied') : t('media.libraryDenied'), [
    { text: t('common.cancel'), style: 'cancel' },
    { text: t('media.openSettings'), onPress: () => void Linking.openSettings() },
  ]);
  return false;
}

export async function pickMedia(source: 'camera' | 'library', { multiple = true, video = true } = {}): Promise<ImagePicker.ImagePickerAsset[]> {
  if (!(await ensurePermission(source))) return [];
  const options: ImagePicker.ImagePickerOptions = {
    mediaTypes: video ? ['images', 'videos'] : ['images'],
    quality: 0.9,
    allowsMultipleSelection: source === 'library' && multiple,
    selectionLimit: multiple ? 10 : 1,
  };
  const result = source === 'camera' && Platform.OS !== 'web' ? await ImagePicker.launchCameraAsync(options) : await ImagePicker.launchImageLibraryAsync(options);
  return result.canceled ? [] : result.assets;
}

/** Uploads one picked asset; throws a translated error for unsupported or too large files. */
export async function uploadAsset(asset: ImagePicker.ImagePickerAsset): Promise<MediaItem> {
  const isVideo = asset.type === 'video' || (asset.mimeType || '').startsWith('video/');
  const kind = isVideo ? 'video' : 'image';
  const name = asset.fileName || `${kind}-${Date.now()}.${isVideo ? 'mp4' : 'jpg'}`;
  if (asset.fileSize && asset.fileSize > MAX_MB[kind] * 1024 * 1024) throw new Error(t('media.tooLarge', { name, mb: MAX_MB[kind] }));
  const type = asset.mimeType || (isVideo ? 'video/mp4' : 'image/jpeg');
  return api.upload<MediaItem>('/media', { uri: asset.uri, name, type });
}
