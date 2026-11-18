# Storing Data on an External Drive

BirdNET-PiPy keeps everything it records in its `data/` folder: the detection
database, your settings, the recordings and the spectrograms. On an SD card that
folder eventually fills the card, and the constant writes wear it out.
`scripts/data-drive.sh` moves the whole folder onto a USB drive or SSD and keeps
the station safe if the drive goes missing.

## Contents

- [Before you start](#before-you-start)
- [Move your data to a new drive](#move-your-data-to-a-new-drive)
- [Use a drive you already mount](#use-a-drive-you-already-mount)
- [If the drive disconnects](#if-the-drive-disconnects)
- [Move your data back, or change drives](#move-your-data-back-or-change-drives)
- [Uninstalling](#uninstalling)

---

## Before you start

- **Install type:** this is for stations installed with `install.sh`. The Home
  Assistant add-on stores its data where Home Assistant puts it.
- **Version:** update the station first, so the service knows how to watch the
  drive.
- **Drive:** a USB SSD is the best choice. A USB flash stick works but is slow,
  and moving the data can take hours.
- **Power:** an SSD powered from the Pi's USB port needs a good power supply
  (the official one for your Pi) or a powered USB hub. Too little power makes the
  drive disconnect.
- **Format:** the drive must be formatted as **ext4**. exFAT, NTFS and FAT
  drives, which is how most drives are sold, cannot hold the database or the
  recordings, so the script formats the drive and **erases everything on it**.
  Copy off anything you want to keep first. An ext4 drive can't be read on
  Windows or macOS without extra software.
- **Space:** the drive needs more free space than your `data/` folder uses. Check
  with `du -sh ~/BirdNET-PiPy/data`.
- **Access:** you run the script over SSH, or in a terminal on the Pi.

---

## Move your data to a new drive

1. Plug in the drive.
2. List the drives the script can use:

   ```bash
   cd ~/BirdNET-PiPy
   sudo scripts/data-drive.sh list
   ```

   ```
   /dev/sda  931.5G  usb  Samsung_SSD_870
   ```

   The disk the Pi boots from is never listed.

3. Set up the drive, using the name from the list:

   ```bash
   sudo scripts/data-drive.sh setup /dev/sda
   ```

   If the drive isn't ext4 yet, the script shows what is on it and asks you to
   type the drive's name (for example `Samsung_SSD_870`) before it formats.
   Typing anything else stops the script without changing anything.

The script then:

- mounts the drive at `/mnt/birdnet-data`, and adds it to `/etc/fstab` so it is
  mounted at every boot
- copies the data while the station keeps recording
- stops the station for a short final copy. This takes a minute or two on an SSD,
  longer on a slow stick.
- starts the station again from the drive

Your original folder is kept on the SD card as `data.internal-<date>`. Once the
station has run well from the drive for a while, delete it to free the space. The
script prints the exact command, for example:

```bash
sudo rm -rf ~/BirdNET-PiPy/data.internal-20261117-101500
```

If the copy is interrupted (Ctrl+C, a lost SSH session), run the same `setup`
command again. It continues where it stopped, and the station keeps running from
the SD card until the move finishes.

To check where the data lives:

```bash
scripts/data-drive.sh status
```

```
data/ -> /mnt/birdnet-data/birdnet
/dev/sda1       916G   61G  809G   7% /mnt/birdnet-data
```

---

## Use a drive you already mount

If the drive is already ext4 and you mount it yourself through `/etc/fstab`,
for example at `/mnt/ssd`, the script can use it without formatting it or
changing your fstab:

```bash
sudo scripts/data-drive.sh setup --mounted /mnt/ssd
```

The data goes into a `birdnet` folder on the drive. Other files on the drive are
left alone.

The script refuses folders that aren't a drive mount listed in `/etc/fstab`, as
well as filesystems that can't hold the data. A drive the desktop mounted on its
own under `/media/...` is not in `/etc/fstab`, so it would not be there after a
reboot. Use `setup /dev/sdX` for those drives instead.

It also warns about two fstab options:

- **`nofail`:** without it, the Pi stops booting when the drive is missing.
- **`x-systemd.wanted-by=<device>`:** without it, a drive that disconnects is
  not mounted again when it comes back, and the station stays stopped until you
  run `sudo mount /mnt/ssd` or reboot.

`setup /dev/sdX` adds both options to the fstab line it writes. To add them to
your own fstab line, get the device name with:

```bash
systemd-escape -p --suffix=device /dev/disk/by-uuid/<your-drive-UUID>
```

---

## If the drive disconnects

The station never records to the SD card while the drive is missing. Writing
there would start a second, empty station and split your data.

- **The drive is unplugged or loses power:** within about 20 seconds the station
  stops, and the web page stops responding.
- **The drive comes back:** it is mounted again and the station starts on its own,
  usually within a minute. This happens automatically for drives set up with
  `setup /dev/sdX`.
- **The Pi boots without the drive:** it still boots normally. The station waits
  and starts as soon as the drive is connected.

While it waits, the service log says so:

```bash
journalctl -u birdnet-pipy -f
```

```
[BIRDNET-SERVICE] Data drive not available at /mnt/birdnet-data; stopping containers until it returns
```

The station sends no notification while it waits, because notifications are sent
by the station itself. If the web page stops responding and the log shows this
message, check the drive's cable and power.

---

## Move your data back, or change drives

To copy the data back onto the SD card:

```bash
sudo scripts/data-drive.sh move-back
```

The station keeps recording during the first copy and stops briefly for the
final one, as with setup. The SD card needs enough free space for the data.

- If the script set up the drive, it also removes the drive's fstab line and
  unmounts it, so you can unplug it.
- If you mount the drive yourself, your fstab line and mount are left as they
  are.

The drive keeps its copy in its `birdnet` folder until you delete it.

To change to another drive, run `move-back`, then `setup` with the new drive.
`setup` refuses a drive whose `birdnet` folder already holds an older copy, so it
never overwrites one. Rename or delete that folder first.

---

## Uninstalling

`./uninstall.sh` keeps your data, so the data on the drive and the drive's fstab
line stay. With `--remove-data` it deletes only the link to the drive, not the
data on the drive.

To remove everything, after uninstalling:

- delete the `birdnet` folder on the drive
- remove the line that contains `/mnt/birdnet-data` from `/etc/fstab`

Alternatively, run `sudo scripts/data-drive.sh move-back` before uninstalling, and
the data is handled like any other station's.
