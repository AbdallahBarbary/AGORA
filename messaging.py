"""In-memory message bus. Agents talk to each other only through it; the feed is what the dashboard shows."""


class MessageBus:
    def __init__(self, keep=300):
        self.inboxes = {}    # agent name -> messages waiting to be read
        self.feed = []       # every message sent, newest first, capped at `keep`
        self.keep = keep
        self.next_id = 1

    def register(self, name):
        """Give an agent an inbox."""
        self.inboxes.setdefault(name, [])

    def send(self, cycle, sender, recipient, kind, body, text):
        """Deliver to one agent, or to every other agent when recipient is 'all', and log it to the feed.

        kind: a short label the receiver dispatches on; body: structured data; text: a readable summary."""
        if recipient != 'all' and recipient not in self.inboxes:
            raise ValueError(f'Unknown recipient: {recipient}')
        message = dict(id=self.next_id, cycle=cycle, sender=sender, recipient=recipient, kind=kind, body=body, text=text)
        self.next_id += 1
        targets = [name for name in self.inboxes if name != sender] if recipient == 'all' else [recipient]
        for name in targets:
            self.inboxes[name].append(message)
        self.feed.insert(0, message)
        del self.feed[self.keep:]
        return message

    def receive(self, name):
        """Hand over, and clear, everything waiting for `name` (oldest first)."""
        messages, self.inboxes[name] = self.inboxes[name], []
        return messages
