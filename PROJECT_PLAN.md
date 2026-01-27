# Flashfood features - planning doc

## Goal
Add configurable features that compliment flashfood app.

## Needs, limits and possible constraints
- No authentication handling - don't want to fuss with security (no access to credit card/purchase features)
- Ideally free - github may be able to poll
- User friendly beyond setup so my friend can use it
- Get notifications on mobile

## Features and priority
1. Notifications for items added at stores near me FAST
2. Notifications for new items/deals that match criteria at configurable stores
3. Easy refund flow (should be straightforward)
4. Quantity visibility (meh)
5. Advanced search (also not really that important)
6. Maybe notifications contain a photo of new item? 


## Build plan potential options

### Notification Delivery
- **Telegram bot** Logic here is that my friend has an iphone and so I either have to do a webapp, make two native apps, or just do tele bot which I know we both already have.
- Sends messages to us directly
- We each have own config
- One notification per item if there's crossover between the two lists of stores (maybe mentions all matching criteria if multiple). Or I could just make those lists mutually exclusive since I'm gonna check everything at my local stores anyway once I get a notification. Simpler.

### Multiple users possible
- Single config file with array of users (future, maybe make this modifiable by each user, permissions. It will just be two of us for now)
- Each user has their own:
  - Telegram chat ID
  - Location
  - Favorite stores list
  - Deal alert stores list (pre-configured)
  - Notification preferences (feature toggle)

### Polling thoughts, needs and concerns
- I need to poll the API fairly often or else it's not better than the built in broken feature they have that's a half hour+ off
- I don't need to poll all the time, just typical store open hours in my timezone (Timezone configurable? My friend's province is an hour difference)
- Is it one polling script per user or one polling script set up for multiple? 
- my github is public so if I use their GH Actions feature I need to figure out how to keep secrets for the sensitive strings - last project got squashed into a giant commit because I had secrets hardcoded in multiple spots during the version history and I didn't want to fix them all.
- Find out how often I can poll if there's a limit on free polling

### Flashfood API
- Is seemingly not readily available. Rats. 
- Tried using HTTP toolkit to see network traffic from my phone but it looks like that traffic is blocked. Tried with CA certificate as well but looks like it doesn't recognize it.
- found this github which is 5 years old but references changing the certificate an APK and reinstalling :https://github.com/patcon/flashfood-api-docs. He's authenticating and I don't want to, and it's old so may not work.
- It does not work, it says it needs an API key. Will do my best to find that now.