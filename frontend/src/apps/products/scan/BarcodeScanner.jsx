import { useEffect, useRef, useState } from 'react';

import { productBarcode } from './barcode.js';
import { getDetector } from './detector.js';

// Time between the end of one reading of the picture and the start of the next.
// A reading is waited for, so a slow one (the WebAssembly reader on a modest
// phone) never piles up behind itself.
const SCAN_INTERVAL_MS = 150;

// The longest side, in pixels, of a photo handed to the reader. A phone's photo
// is some twelve megapixels, which the reader would only take longer over.
const PICTURE_MAX_SIDE = 1600;

// A photo of at most PICTURE_MAX_SIDE, as the reader can take it.
async function smallPicture(file) {
  const picture = await createImageBitmap(file);
  const scale = PICTURE_MAX_SIDE / Math.max(picture.width, picture.height);
  if (scale >= 1) return picture;
  const small = await createImageBitmap(picture, {
    resizeWidth: Math.round(picture.width * scale),
    resizeHeight: Math.round(picture.height * scale),
    resizeQuality: 'high',
  });
  picture.close();
  return small;
}

/**
 * Reads the barcode of a product through the camera, live, and calls
 * `onDetect(barcode, 'camera')` each time it sees one (as long as it stays in
 * view, that is many times a second: what to make of it is the caller's). A
 * photo is `onDetect(barcode, 'picture')`, once, for a person who asked for it.
 *
 * The browser gives a page the live camera only over https (or on localhost).
 * Where it does not, or the person refused it, a button takes a photo of the
 * barcode with the phone's own camera app instead, which works on any page.
 *
 * @param {object} props
 * @param {Record<string, string>} props.labels Translated by ProductListView.
 * @param {(barcode: string, source: 'camera' | 'picture') => void} props.onDetect
 */
export function BarcodeScanner({ labels, onDetect }) {
  const videoRef = useRef(null);
  const pictureRef = useRef(null);
  // The latest, so that a new callback does not restart the camera.
  const onDetectRef = useRef(onDetect);
  const [live, setLive] = useState(false);
  // The keys of the labels saying what is wrong, if anything is: with the
  // camera, and with the photo last taken.
  const [cameraProblem, setCameraProblem] = useState(null);
  const [pictureProblem, setPictureProblem] = useState(null);
  const [reading, setReading] = useState(false);

  useEffect(() => {
    onDetectRef.current = onDetect;
  });

  useEffect(() => {
    let cancelled = false;
    let stream = null;
    let timer = null;

    const fail = (key) => {
      if (!cancelled) setCameraProblem(key);
    };

    async function watch(detector, video) {
      if (cancelled) return;
      if (video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA) {
        try {
          const code = productBarcode(await detector.detect(video));
          if (code && !cancelled) onDetectRef.current(code, 'camera');
        } catch (error) {
          // A frame that cannot be read is not the end of the scan.
          console.error(error);
        }
      }
      if (!cancelled)
        timer = setTimeout(watch, SCAN_INTERVAL_MS, detector, video);
    }

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        fail(window.isSecureContext ? 'scanCameraFailed' : 'scanNeedsHttps');
        return;
      }
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          audio: false,
          video: {
            // The camera on the back; any camera at all on a computer.
            facingMode: { ideal: 'environment' },
            width: { ideal: 1280 },
            height: { ideal: 720 },
            // A barcode is read at arm's length: let the phone keep it in focus.
            advanced: [{ focusMode: 'continuous' }],
          },
        });
      } catch (error) {
        fail(
          error.name === 'NotAllowedError'
            ? 'scanCameraDenied'
            : 'scanCameraFailed',
        );
        return;
      }
      if (cancelled) {
        stream.getTracks().forEach((track) => track.stop());
        return;
      }

      const video = videoRef.current;
      video.srcObject = stream;
      try {
        await video.play();
      } catch (error) {
        // Interrupted by the scanner being closed, or refused by the browser.
        console.error(error);
        fail('scanCameraFailed');
        return;
      }
      if (!cancelled) setLive(true);

      let detector;
      try {
        detector = await getDetector();
      } catch (error) {
        console.error(error);
        fail('scanReaderError');
        return;
      }
      watch(detector, video);
    }

    start();

    return () => {
      cancelled = true;
      clearTimeout(timer);
      stream?.getTracks().forEach((track) => track.stop());
      if (videoRef.current) videoRef.current.srcObject = null;
    };
  }, []);

  async function readPicture(event) {
    const [file] = event.target.files;
    // So that the same photo, taken again, is a change.
    event.target.value = '';
    if (!file) return;

    setPictureProblem(null);
    setReading(true);
    try {
      const detector = await getDetector();
      const picture = await smallPicture(file);
      const code = productBarcode(await detector.detect(picture));
      picture.close();
      if (code) onDetectRef.current(code, 'picture');
      else setPictureProblem('scanPictureEmpty');
    } catch (error) {
      console.error(error);
      setPictureProblem('scanReaderError');
    } finally {
      setReading(false);
    }
  }

  return (
    <div>
      {/* Always there for the effect to find, and out of sight until the
          camera is running. */}
      <video
        ref={videoRef}
        className={live ? 'w-100 rounded bg-dark mb-2' : 'd-none'}
        style={{ maxHeight: '60vh', objectFit: 'contain' }}
        playsInline
        muted
        aria-label={labels.scanCamera}
      />
      {live && !cameraProblem && (
        <p className="small text-body-secondary mb-2">{labels.scanHint}</p>
      )}
      {!live && !cameraProblem && (
        <p className="text-body-secondary mb-2">{labels.scanStarting}</p>
      )}
      {[cameraProblem, pictureProblem].filter(Boolean).map((key) => (
        <p key={key} className="text-danger mb-2" role="alert">
          {labels[key]}
        </p>
      ))}
      <button
        type="button"
        // The way left when the camera cannot be had live: then it is the action.
        className={`btn btn-sm ${cameraProblem ? 'btn-primary' : 'btn-outline-secondary'}`}
        disabled={reading}
        onClick={() => pictureRef.current.click()}
      >
        <i className="fa-solid fa-camera" /> {labels.scanTakePicture}
      </button>
      {/* "capture" has the phone open its camera app and hand back the photo. */}
      <input
        ref={pictureRef}
        type="file"
        accept="image/*"
        capture="environment"
        className="d-none"
        aria-label={labels.scanTakePicture}
        onChange={readPicture}
      />
    </div>
  );
}
