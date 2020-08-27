# bdtask

Generate bluray encode task and manage them.
Used for PT uploader.

## TODO

- [ ] script to read settings.yaml and run vspipe + x265
- [ ] script to generate .nfo
- [ ] log and task management
- [ ] argparse refine

## Dependencies

- bdinfo
- x265

## Tipical Task Pipeline

- prepare bluray
- task initiation -- will be done `bdtask.py`
    - generate `extract.sh`
    - mkdir and other preparation
- extract components:
    - audio:
        - transcode PCM to FLAC
        - transcode DTS-HD to AC3 @640kbps
        - copy commentary traack of AC3 @192kbps
    - subtitle:
        - copy HDMV/PGS subtitle
- check video source:
    - crop black line to right ratio
    - fix dirty lines
    - other fix
- crf test for sample (>5000 frames)
- choose proper crf value
- [optional] test for other x265 params
- video encode in full length
- mkv mux test
- search, test and fix timeline for addtional subtitles
- mkv mux final
- screenshot
    - screenshot for [source, filtered, encoded] comparision
    - upload screenshots to image host and get urls
- generate .nfo file
- download film poster
- generate a torrent
- fill intro and upload to pt site
- download torrent and start seeding


## Usage

### Generate Task

Generate a bluray encode task

### Manage Task

Check pipeline status of current task, call other script to do next job in pipeline