# Exposing Home Assistant to the Internet for use with neubot
neubot requires that your Home Assistant instance is externally accessible, and there are various ways to do this. 

## Cloudflared Addon (recommended)
**Difficulty**: Moderate

**Requirements**
- Free Cloudflare Account
- Domain name connected to your Cloudflare account (please note that domains from **Freenom** cannot be used, please find another registrar)
- Home Assistant Installation with **addons** support

**Step 1**

Click the button below and follow the prompts to add the Cloudflared addon repository and install the Cloudflared addon. Do not start it yet.

[![Open your Home Assistant instance and show the dashboard of an add-on.](https://my.home-assistant.io/badges/supervisor_addon.svg)](https://my.home-assistant.io/redirect/supervisor_addon/?addon=9074a9fa_cloudflared&repository_url=https%3A%2F%2Fgithub.com%2Fbrenner-tobias%2Fha-addons)

**Step 2**

Open the **Configuration tab** of the Cloudflared addon and in the **first box** enter your domain. This can be the root of your domain (example.com) or a subdomain (home.example.com), do not include a protocol such as https://example.com.

**Step 3**

Go back to the **Info** tab of the Cloudflared addon and press the **Start** button

**Step 4**

Now navigate to the **Log** tab and look for the following line (it should be close to the bottom)

```bash
[16:27:10] NOTICE: 
Please open the following URL and log in with your Cloudflare account:
https://dash.cloudflare.com/argotunnel?...
```

Copy the link provided, sign into Cloudflare if needed and authorise the Argo tunnel. Once completed, you should see this message in the logs

```bash
[16:27:44] INFO: Authentication successfull, moving auth file to the '/data' folder
```

**Step 5**

Since the addon runs locally, Home Assistant doesn't trust Cloudflared yet. To make it trust Cloudflared, add the following to the end of your `/config/configuration.yaml`:

```yaml
http:
  use_x_forwarded_for: true
  trusted_proxies:
    - 172.30.33.0/24
```

If you are using non-standard hosting methods of HA (e.g. Proxmox), you might have to add another IP(range) here. Check your HA logs after attempting to connect to find the correct IP.

> [!IMPORTANT] 
>
> The add-on reads your `configuration.yaml` to detect your Home Assistant port and if SSL is used. **If you have changed the default port or enabled SSL in the [HTTP integration](https://www.home-assistant.io/getting-started/configuration/)**, you must keep the entire `http:` block directly in `configuration.yaml`. Do not move it to a `!include file` or a `!include_dir_*` directory, as the add-on does not follow additional YAML files.

Remember to restart Home Assistant after editing `configuration.yaml`

**Step 6**

Navigate to the URL you entered into the configuration earlier and confirm you can access Home Assistant.

## Port Forwarding (not recommended)
**Difficulty**: Easy to Moderate

**Requirements**: 
- Public IP address
- Administrator access to your router

> [!CAUTION]
>
> Exposing Home Assistant directly to the internet is not recommended as you are likely to encounter many malicious bots attempting to exploit vulnerabilities in Home Assistant. Go forward at your own risk.

**Step 1**

Follow your router's user manual to forward port **8123** (default port, this will be different if you have changed it for some reason) on your router.

**Step 2**

Ensure Home Assistant is accessible by attempting to navigate to `http://your-public-ip:8123`