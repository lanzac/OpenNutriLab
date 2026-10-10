// The labels of the scanner as ProductListView hands them over, in French (the
// real catalogue entries, so a regression back to hardcoded English fails the
// tests that use them).
export const scanLabels = {
  scanProduct: 'Scanner un produit',
  scanClose: 'Fermer le scanner',
  scanCamera: 'Caméra',
  scanStarting: 'Démarrage de la caméra…',
  scanHint: 'Placez le code-barres du produit devant la caméra.',
  scanTakePicture: 'Prendre le code-barres en photo',
  scanNeedsHttps:
    'La caméra ne peut servir en direct que sur une page sécurisée (https). Prenez plutôt le code-barres en photo.',
  scanCameraDenied:
    'La caméra est bloquée. Autorisez-la pour ce site dans les réglages du navigateur, ou prenez le code-barres en photo.',
  scanCameraFailed:
    "La caméra n'a pas pu démarrer. Prenez plutôt le code-barres en photo.",
  scanReaderError: "Le lecteur de codes-barres n'a pas pu être chargé.",
  scanPictureEmpty:
    "Aucun code-barres n'a été trouvé sur la photo. Réessayez de plus près, les barres bien nettes.",
  scanAdded: '« %(name)s » a été ajouté à votre inventaire.',
  scanAlready: '« %(name)s » est déjà dans votre inventaire.',
  scanUnknown: "Le code %(barcode)s n'est pas encore dans le catalogue.",
  scanCreate: 'Créer le produit',
  inventoryError: "Votre inventaire n'a pas pu être modifié.",
};
