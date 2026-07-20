# Running Parabellum on Your Phone

You don't need to install an app store, publish to Google Play, or use
Capacitor. Because Parabellum is a real web app, your phone can just
open it in a browser — the same way your PC does.

Both devices need to be on the **same Wi-Fi network** (your home
Wi-Fi is fine; a school/office network sometimes blocks device-to-device
access — see troubleshooting at the bottom if that happens).

---

## One-time setup (5 minutes)

### 1. Find your PC's local IP address

On Windows, open a terminal and run:

```
ipconfig
```

Look for a section like **"Wireless LAN adapter Wi-Fi"** (or "Ethernet"
if you're plugged in). Find the line that says **IPv4 Address**. It will
look something like:

```
IPv4 Address . . . . . . . . . . . : 192.168.1.42
```

That number (`192.168.1.42` — yours will differ) is your PC's address
on the Wi-Fi network. Write it down.

### 2. Let Windows Firewall allow the connection

The first time your Flask app tries to accept a connection from another
device, Windows Firewall will pop up a dialog:

> *"Windows Defender Firewall has blocked some features of Python..."*

Check **"Private networks"** and click **Allow access**.

If you missed that dialog, or you're not sure whether you clicked
"Allow" or "Cancel", you can add the rule manually:
Start menu → search **"Firewall & network protection"** → **"Allow an
app through firewall"** → find Python in the list → check the
**Private** box.

---

## Every time you want to use it from your phone

### On your PC:

```
cd "C:\Users\Kurt Angelu Perez\Downloads\Parabellum"
python app.py
```

Leave the terminal window open — as long as it's running, the server
is up.

### On your phone:

Open any browser (Chrome, Safari, etc.) and go to:

```
http://192.168.1.42:5000
```

(Replace `192.168.1.42` with your PC's actual IP from step 1.
The `:5000` at the end is important — that's the port number Flask
listens on.)

You'll get the same landing page as on your PC, and the same login,
forecasting, everything. Sign in with a demo account (see the main
README for credentials).

**Tip:** on your phone, after opening the site in Chrome, tap the
three-dot menu → **"Add to Home screen"**. It creates an icon that
looks and behaves like an installed app — full-screen, no browser
address bar. That gives you the "app-like" feel without the actual
Capacitor build.

---

## Troubleshooting

**"This site can't be reached"**
- Check both devices are on the same Wi-Fi. Guest networks on the same
  router are often walled off from the main network.
- Make sure Flask is actually running (the terminal window on your PC
  should be showing log lines).
- Double-check the IP. Some routers reassign IP addresses periodically,
  so if it worked yesterday and doesn't today, re-run `ipconfig`.

**Windows Firewall keeps blocking it**
- Add Python to allowed apps manually (see step 2 above).
- Some corporate/school laptops have policy locks that override this —
  if you can't get past the firewall on your normal laptop, try a
  personal one, or use USB tethering (your phone shares its data with
  the PC, putting them on the same "network").

**"Can I use it away from my Wi-Fi network?"**
Not directly — the address `192.168.x.x` only works on the local
network. For remote access you'd need to either deploy the app to a
cloud host, or use a tunneling tool like ngrok. Neither is needed for
your capstone defense, since panelists will be in the same room.
