Planning document - brainstorming

There is an app called flashfood that sells food at a discount. I would like a way to create features that either don't exist or don't really work in the original.

Features to add:
I want it to be configurable that I get a notification when something new is posted at a list of stores that I monitor (list should be configurable somehow - list of ids or something)

I want it to be configurable  to get a notification when a store nearby me (definition of nearby should be configurable) publishes an item for less than $(insert configurable amount)
    if I do this by radius the problem is that it will show me stuff in laval, which takes longer to get to than a place
    that's technically farther away but doesn't involve crossing a body of water. There's probably only like 30 stores I'd
    be willing to travel to if they had a great deal so maybe a list too.

I want it to be configurable for me to get a notification when a store nearby me lists an item that is discounted more than (insert configurable amount %) 
    same idea as above, maybe shared logic

I want to be able to apply for a refund easily instead of the current flow which is searching their website and filling out a form. Upside is that this does not require authentication in my experience.
    They make you go through their knowledge articles and it's annoying and I'm pretty sure it's just a URL

I want to see the quantity of a given item that is available without having to hit the + until it maxes out
    if I'm doing a notification based mvp I gotta think about how or if I even care about that. Maybe if the notification has a photo in it and an available quantity? Not high priority.

I want to be able to search items at stores nearby me based on the following criteria
expiry date (after input date)
distance from me
    I should add to this there's probably way more I could do with it
    But it's also low priority because it's not really notification friendly for mvp

Here are some things I would like to be possible
my code does not have to handle authentication because I'd rather not fuss with security
Accessing these features in an app like setting, BUT the core stuff I'm interested in could just be notification based.
    Probably if I can configure it that would be acceptable, I can always go to the app to do the actual perusing.

I would like to be able to share this project with non technical friends so they can use it - I shouldn't build anything too complicated.
I would like to be able to access these features primarily from my phone
    currently the flashfood app doesn't send a notification at the right time when a favourite store posts
    I want it more instantly but I'm not gonna run a server chez moi to do it if I'm the only person using it. 
    Maybe github hosting idk.
