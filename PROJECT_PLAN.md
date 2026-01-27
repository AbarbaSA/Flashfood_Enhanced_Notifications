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