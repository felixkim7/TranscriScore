# Project Proposal: Transformer-Based Music Transcription and MusicXML Sheet Generation System

## 1. Introduction

Music transcription is the process of converting performed music into symbolic notation. Traditionally, this requires trained musicians to listen to an audio recording, identify each musical part, determine the pitch and rhythm, and manually write the result as sheet music. This becomes especially difficult when the audio contains multiple sound sources, such as vocals, piano, guitar, bass, drums, or orchestral sections.

Many amateur musicians also have hard times finding sheet music for the pieces they wish to perform, and even when they do, sometimes the instrument they play doesn't match the instrument of the sheet music.

This project proposes a music transcription and sheet music generation system that converts short audio recordings into editable digital notation. The system combines modern music information retrieval methods, transformer-based audio models, automatic music transcription models, symbolic music processing, and MusicXML rendering. Instead of treating audio-to-sheet-music conversion as one single problem, the project divides it into multiple stages: audio preprocessing, source separation, stem classification, audio-to-MIDI transcription, rhythm quantization, MusicXML generation, score rendering, language-model-based music analysis, and user correction.

The main goal is to build a practical and technically deep prototype that demonstrates applied machine learning, audio processing, symbolic music representation, and interactive software design.

## 2. Project Objective

The objective of this project is to build an end-to-end system that can receive an audio file and generate an editable sheet music draft from it.

The system aims to:

1. Accept short music audio files as input.
2. Preprocess audio using signal-processing methods such as waveform conversion, spectrogram extraction, mel-spectrogram extraction, onset detection, and tempo estimation.
3. Separate mixed audio into stems using Demucs or Hybrid Transformer Demucs.
4. Classify separated stems using an instrument or stem-role classification model.
5. Transcribe selected stems into MIDI-like note events using automatic music transcription models such as Spotify Basic Pitch and ByteDance piano_transcription.
6. Clean the raw transcription using beat tracking, rhythm quantization, duration simplification, rest insertion, and note-event filtering.
7. Convert cleaned symbolic note data into MusicXML using music21 or partitura.
8. Render the generated MusicXML using OpenSheetMusicDisplay and MuseScore CLI.
9. Allow users to correct the generated notation and export the final result as MusicXML, MIDI, PDF, SVG, PNG, or MuseScore file.

The system is intended to produce an editable first draft of sheet music, not a perfect final transcription.

## 3. Project Explanation

The proposed project is an audio-to-score generation pipeline. The system starts with an uploaded audio file and gradually transforms it into symbolic music data.

First, the audio is converted into a standard internal format. Libraries such as librosa, torchaudio, Essentia, or madmom can be used to extract waveform data, spectrograms, mel-spectrograms, onset information, tempo, and beat positions. These features are useful for both visualization and later rhythm cleanup.

Next, the system uses a source separation model. The main model considered for this stage is Demucs, especially Hybrid Transformer Demucs. Demucs separates a mixed music signal into stems such as vocals, drums, bass, and other accompaniment. This is important because automatic transcription is more reliable when performed on a cleaner individual stem rather than on the full mixed audio.

After separation, each stem is passed through a stem labeling module. This module can be implemented using a mel-spectrogram-based convolutional neural network, an Audio Spectrogram Transformer-style classifier, YAMNet-style audio classification, or a fine-tuned Hugging Face audio classification model. The goal is to label each stem with a musical role such as vocal melody, bass, drums, piano accompaniment, guitar accompaniment, or string-like accompaniment. The user can also manually confirm or edit the predicted label.

The selected stem is then transcribed into MIDI-like note events. For general melody and instrumental transcription, the project can use Spotify Basic Pitch. Basic Pitch estimates pitch, onset time, offset time, duration, velocity, and pitch bend information from audio. For piano-specific input, the system can optionally use ByteDance piano_transcription, which is specialized for piano note and pedal transcription.

The raw transcription output is not yet suitable for sheet music. It usually contains note timings in seconds, irregular note lengths, small false notes, and performance timing variations. Therefore, the project includes a symbolic cleanup stage. This stage uses beat tracking, tempo estimation, onset alignment, quantization, duration simplification, rest insertion, and measure grouping. Libraries such as music21, pretty_midi, mido, librosa, and madmom can be used for this stage.

After the transcription is cleaned, the note events are converted into MusicXML. MusicXML is used because it is widely supported by notation software and can store parts, measures, clefs, key signatures, time signatures, notes, rests, ties, and instrument names. The main libraries considered for this stage are music21 and partitura.

The generated MusicXML is then rendered as sheet music. OpenSheetMusicDisplay can be used for browser-based MusicXML rendering, while MuseScore CLI can be used to export high-quality PDF, PNG, SVG, MIDI, and MSCZ files. This makes the system practical for real musicians because the result is not only raw MIDI, but editable and printable notation.


## 4. Detailed Project Pipeline

Audio File Upload
        ↓
Audio Preprocessing with librosa / torchaudio / Essentia / madmom
        ↓
Source Separation using Demucs / Hybrid Transformer Demucs
        ↓
Stem Role Classification using CNN / Audio Spectrogram Transformer / YAMNet / Hugging Face fine-tuned classifier
        ↓
Audio-to-MIDI Transcription using Spotify Basic Pitch
        ↓
Optional Piano-Specific Transcription using ByteDance piano_transcription
        ↓
Beat Tracking + Rhythm Quantization + Note Cleanup
        ↓
MusicXML Generation using music21 / partitura
        ↓
Score Rendering using OpenSheetMusicDisplay + MuseScore CLI
        ↓
User Correction + Export


## 5. Pipeline Explanation

### 5.1 Audio File Upload

The user uploads an audio file to the system. Supported formats may include WAV, MP3, FLAC, and M4A. The first version of the project will focus on short clips of approximately 1 to 3 minutes.

The target input types are:

solo piano
vocal melody
bass line
simple pop or band arrangement
simple accompaniment stem


Full orchestral transcription can be discussed as a future extension, but it should not be the first development target.

### 5.2 Audio Preprocessing

The uploaded file is converted into a consistent audio format. This step may include:

sample rate normalization
mono/stereo conversion
loudness normalization
waveform extraction
spectrogram generation
mel-spectrogram generation
onset detection
tempo estimation
beat tracking

Possible libraries include:

librosa
torchaudio
Essentia
madmom
ffmpeg

The spectrogram and mel-spectrogram can also be used as input representations for classification models.

### 5.3 Source Separation with Demucs

The source separation stage uses Demucs or Hybrid Transformer Demucs to split the original mixed audio into stems.

Expected output:

vocals.wav
drums.wav
bass.wav
other.wav

Demucs is suitable for this project because it is a music source separation model designed to isolate vocals, drums, bass, and accompaniment from a mixed recording. Hybrid Transformer Demucs is especially relevant because it combines waveform-domain and spectrogram-domain modeling with transformer layers.

This stage improves the later transcription process because a selected stem is usually easier to transcribe than a full mixed track.

### 5.4 Stem Role Classification

After source separation, each stem is classified according to its musical role.

Possible methods:

mel-spectrogram CNN classifier
Audio Spectrogram Transformer-style classifier
YAMNet-style audio classifier
fine-tuned Hugging Face audio classification model

Example labels:

vocal melody
bass
drums
piano accompaniment
guitar accompaniment
string-like accompaniment
unknown / mixed accompaniment

This stage is important because each type of stem should be handled differently.

For example:

vocal melody → monophonic melody transcription
bass → bass clef transcription
piano → polyphonic piano transcription
drums → percussion analysis or skipped in first version
other/accompaniment → rough polyphonic transcription

The user can manually confirm or correct the predicted label before transcription.

### 5.5 Audio-to-MIDI Transcription with Basic Pitch

The selected stem is passed into an automatic music transcription model.

The main model for the first version is:

Spotify Basic Pitch

Basic Pitch converts audio into MIDI-like note events. The output can include:

pitch
onset time
offset time
duration
velocity
pitch bend

Example output format:
json
[
  {
    "pitch": 60,
    "note": "C4",
    "onset": 1.02,
    "offset": 1.48,
    "duration": 0.46,
    "velocity": 82
  }
]

This stage is the bridge between audio processing and symbolic music processing.

### 5.6 Optional Piano Transcription with ByteDance piano_transcription

If the stem is classified as piano, the system can optionally use:

ByteDance piano_transcription

This model is specialized for piano automatic music transcription. It can be used as an alternative to Basic Pitch for piano-focused input.

The system can choose the transcription model based on the stem label:

vocal / melody → Basic Pitch
bass → Basic Pitch + bass clef post-processing
piano → ByteDance piano_transcription or Basic Pitch
other accompaniment → Basic Pitch rough transcription
drums → future percussion transcription module

This makes the project more technically meaningful because the pipeline adapts its transcription method to the musical role of the stem.

### 5.7 Beat Tracking, Rhythm Quantization, and Note Cleanup

Raw transcription results are not directly readable as sheet music. The system must convert performance timing into musical notation.

This stage includes:

tempo estimation
beat grid estimation
time signature estimation
onset alignment
duration quantization
short false note removal
repeated note merging
rest insertion
tie generation
measure grouping
clef selection

Example:

Raw transcription:
C4 starts at 1.023 seconds and ends at 1.491 seconds

Cleaned notation:
C4 quarter note

Possible tools:

librosa
madmom
pretty_midi
mido
music21

This is one of the most important original engineering parts of the project. It shows that the project is not only calling a pretrained model, but also transforming raw model output into readable musical notation.

### 5.8 MusicXML Generation

The cleaned note events are converted into a symbolic score.

Possible libraries:

music21
partitura

The system should generate:

parts
measures
notes
rests
clefs
key signatures
time signatures
tempo markings
instrument names

Final output:

generated_score.musicxml

MusicXML is chosen because it can be opened and edited in notation software such as MuseScore.

### 5.9 Score Rendering with OpenSheetMusicDisplay and MuseScore CLI

The generated MusicXML is rendered in two ways.

For browser preview:

OpenSheetMusicDisplay

For high-quality export:

MuseScore CLI

The system can export:

PDF
PNG
SVG
MIDI
MSCZ
MusicXML

This makes the system more useful because users can view, edit, print, and reuse the generated score.

### 5.10 User Correction and Export

The system should support human correction because automatic transcription is not perfect.

Correction features may include:

change pitch
change note duration
delete note
merge notes
split notes
change clef
change instrument label
regenerate MusicXML

After correction, the user can export:

MusicXML
MIDI
PDF
PNG
SVG
MSCZ
separated audio stems
note-event JSON

This creates a human-in-the-loop transcription workflow.

## 6. Expected Technology Stack

### Backend

Python
FastAPI
PyTorch
TensorFlow / ONNX runtime if needed for Basic Pitch
librosa
torchaudio
Essentia
madmom
Demucs / Hybrid Transformer Demucs
Spotify Basic Pitch
ByteDance piano_transcription
music21
partitura
pretty_midi
mido
MuseScore CLI
ffmpeg

### Machine Learning and Model Tools

PyTorch
TensorFlow
Hugging Face Transformers
Hugging Face Hub
Audio Spectrogram Transformer-style classifier
YAMNet-style classifier
fine-tuning for stem/instrument classification
pretrained transcription models

### LLM / Generative Analysis Layer

OpenAI API or local LLM
LangChain
RAG with a small music theory knowledge base
prompt templates based on structured music analysis

### Frontend

React
JavaScript / TypeScript
OpenSheetMusicDisplay
Waveform viewer
Stem audio player
Score preview panel
Correction interface
Export buttons

### Storage

local file storage for prototype
SQLite for project history
JSON for intermediate note events
PostgreSQL for expanded version

## 7. Expected Features

The final Level 2 system should include:

audio upload
audio preprocessing
Demucs-based source separation
stem playback
transformer/CNN-based stem classification
Basic Pitch audio-to-MIDI transcription
optional piano transcription with ByteDance piano_transcription
beat tracking
rhythm quantization
note cleanup
MusicXML generation
OpenSheetMusicDisplay browser preview
MuseScore CLI export
LLM-based music explanation
user correction interface
MusicXML / MIDI / PDF / PNG / SVG / MSCZ export

## 8. Project Scope and Limitations

The project focuses on short audio clips and selected musical stems. It does not claim to perfectly transcribe all possible music.

The first version will focus on:

vocal melody
bass line
solo piano
simple accompaniment
simple mixed audio separated into broad stems

The system will not initially focus on:

full orchestral score reconstruction
separating every individual orchestral instrument
perfect drum notation
complex jazz transcription
large-scale commercial transcription accuracy

These can be discussed as future extensions.

The strength of the project is not that it perfectly solves transcription. Its strength is that it connects several difficult components into one usable workflow:

source separation
stem classification
audio-to-MIDI transcription
symbolic cleanup
MusicXML generation
score rendering
LLM-based explanation
human correction

## 9. Expected Outcome

The expected result is a web-based music transcription assistant. A user uploads an audio file, the system separates it into stems, classifies each stem, transcribes a selected stem, cleans the rhythm, generates MusicXML, renders the score, provides a music explanation, and allows the user to correct and export the result.

This project demonstrates skills in:

machine learning
transformer-based audio modeling
audio signal processing
music information retrieval
symbolic music representation
MusicXML
frontend/backend development
LLM application design
human-computer interaction

It is suitable as a major portfolio project for AI, music technology, creative technology, software engineering, internship applications, and graduate school preparation.

## 10. Conclusion

This project proposes a transformer-based music transcription and MusicXML generation system that converts short audio recordings into editable sheet music. The system combines Demucs-based source separation, stem classification, Basic Pitch transcription, optional piano-specific transcription, rhythm quantization, symbolic music processing, MusicXML generation, MuseScore/OpenSheetMusicDisplay rendering, and LLM-based music analysis.
