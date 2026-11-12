console.log("Hello bhai")
const a=20
const b=40;
console.log(a+b)
console.log("JS maths is broken")

const sev={
    nama:"Aryan",
    roll_no:"5723783"
}
console.table(sev);
console.dir()
console.error('okay so this is an error')

function newly(params){
    console.log('this is the param object', params)
    let a=params.say;
    let b=params.user
    // return a+' '+b;

    console.log("Other way of destructing");

    // keys should be same or
    let {say, user}=params;
    return user +' says '+ say;
}
const hello={
    say:"Hello",
    user:'Devv',
}
console.log(newly(hello))